module c_fsm_oh_v95_4 (clk, rst, go, alt, done, odd);
  input clk, rst, go, alt;
  output done, odd;
  parameter S0 = 4'b0001;
  parameter S1 = 4'b0010;
  parameter S2 = 4'b0100;
  parameter S3 = 4'b1000;
  reg [3:0] st;
  reg [3:0] nx;
  always @(st or go or alt) begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S3;
      end
      default: nx = S0;
    endcase
  end
  always @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S3);
  assign odd = (st == S1) | (st == S3);
endmodule
