module top (
    input [0:0] clk,
    input [0:0] go,
    input [0:0] abort,
    output reg [0:0] last,
    output reg [0:0] busy
);
  localparam S0 = 2'd0;
  localparam S1 = 2'd1;
  localparam S2 = 2'd2;
  localparam S3 = 2'd3;
  reg [1:0] st;
  reg [1:0] ns;
  always @* begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S3);
    busy <= (ns != S0);
  end
endmodule
