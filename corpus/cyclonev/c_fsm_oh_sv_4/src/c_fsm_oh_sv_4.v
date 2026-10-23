module c_fsm_oh_sv_4 (input logic clk, rst, go, alt, output logic done, odd);
  typedef enum logic [3:0] {S0 = 4'b0001, S1 = 4'b0010, S2 = 4'b0100, S3 = 4'b1000} state_t;
  state_t st, nx;
  always_comb begin
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
  always_ff @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S3);
  assign odd = (st == S1) | (st == S3);
endmodule
